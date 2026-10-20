(function () {
    function bindPortalDrawer() {
        const toggle = document.querySelector("[data-portal-nav-toggle]");
        const drawer = document.querySelector("[data-portal-drawer]");
        const dismissButtons = document.querySelectorAll("[data-portal-nav-dismiss], [data-portal-nav-close]");
        const nav = document.querySelector("[data-portal-nav]");
        if (!toggle || !drawer) {
            return;
        }

        function setOpen(open) {
            toggle.setAttribute("aria-expanded", String(open));
            drawer.classList.toggle("is-open", open);
            document.body.classList.toggle("drawer-is-open", open);
        }

        toggle.addEventListener("click", () => {
            setOpen(toggle.getAttribute("aria-expanded") !== "true");
        });

        dismissButtons.forEach((button) => {
            button.addEventListener("click", () => setOpen(false));
        });

        if (nav) {
            nav.querySelectorAll("a").forEach((link) => {
                link.addEventListener("click", () => setOpen(false));
            });
        }

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                setOpen(false);
            }
        });
    }

    function bindNotificationMenu() {
        const menu = document.querySelector("[data-notification-menu]");
        const trigger = menu?.querySelector("[data-notification-trigger]");
        const panel = menu?.querySelector("[data-notification-panel]");
        const list = panel?.querySelector(".notification-list");
        if (!menu || !trigger || !panel) {
            return;
        }

        function positionPanel() {
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;
            const edge = 12;
            const gap = 14;
            const panelWidth = Math.min(410, viewportWidth - (edge * 2));
            const triggerRect = trigger.getBoundingClientRect();
            const desktop = window.matchMedia("(min-width: 861px)").matches;

            panel.style.position = "fixed";
            panel.style.width = `${panelWidth}px`;
            panel.style.right = "auto";
            panel.style.left = `${edge}px`;
            panel.style.top = `${edge}px`;

            const panelHeight = panel.offsetHeight;
            const preferredLeft = desktop
                ? triggerRect.right + gap
                : triggerRect.right - panelWidth;
            const preferredTop = desktop
                ? triggerRect.top - 8
                : triggerRect.bottom + 10;
            const maxLeft = Math.max(edge, viewportWidth - panelWidth - edge);
            const maxTop = Math.max(edge, viewportHeight - panelHeight - edge);
            const left = Math.min(Math.max(edge, preferredLeft), maxLeft);
            const top = Math.min(Math.max(edge, preferredTop), maxTop);

            panel.style.left = `${Math.round(left)}px`;
            panel.style.top = `${Math.round(top)}px`;
        }

        function prepareOpenPanel() {
            menu.classList.add("is-positioning");
            window.requestAnimationFrame(() => {
                if (!menu.open) return;
                if (list) list.scrollTop = 0;
                positionPanel();
                menu.classList.remove("is-positioning");
            });
        }

        function setExpanded(open) {
            trigger.setAttribute("aria-expanded", String(open));
            menu.classList.toggle("is-open", open);
            if (open) prepareOpenPanel();
            else menu.classList.remove("is-positioning");
        }

        trigger.addEventListener("click", () => {
            if (!menu.open) menu.classList.add("is-positioning");
        });
        menu.addEventListener("toggle", () => setExpanded(menu.open));
        document.addEventListener("pointerdown", (event) => {
            if (menu.open && !menu.contains(event.target)) {
                menu.open = false;
            }
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && menu.open) {
                menu.open = false;
                trigger.focus();
            }
        });
        window.addEventListener("resize", () => {
            if (menu.open) positionPanel();
        });
        window.visualViewport?.addEventListener("resize", () => {
            if (menu.open) positionPanel();
        });
        setExpanded(menu.open);
    }

    function bindSignOutConfirmation() {
        const form = document.querySelector("[data-logout-form]");
        const modal = document.querySelector("[data-logout-modal]");
        const dialog = modal?.querySelector("[role='dialog']");
        const confirmButton = modal?.querySelector("[data-logout-confirm]");
        const cancelButtons = modal?.querySelectorAll("[data-logout-close]") || [];
        if (!form || !modal || !dialog || !confirmButton) {
            return;
        }

        let returnFocus = null;
        let isSubmitting = false;

        function focusableElements() {
            return Array.from(
                dialog.querySelectorAll(
                    "button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"
                )
            ).filter((element) => !element.hidden);
        }

        function openModal() {
            returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
            modal.hidden = false;
            document.body.classList.add("modal-is-open");
            window.requestAnimationFrame(() => confirmButton.focus());
        }

        function closeModal() {
            if (isSubmitting) return;
            modal.hidden = true;
            document.body.classList.remove("modal-is-open");
            returnFocus?.focus();
        }

        form.addEventListener("submit", (event) => {
            if (isSubmitting) return;
            event.preventDefault();
            openModal();
        });

        cancelButtons.forEach((button) => button.addEventListener("click", closeModal));

        confirmButton.addEventListener("click", () => {
            if (isSubmitting) return;
            isSubmitting = true;
            confirmButton.disabled = true;
            confirmButton.setAttribute("aria-busy", "true");
            const label = confirmButton.querySelector("span");
            if (label) label.textContent = "Signing out…";
            HTMLFormElement.prototype.submit.call(form);
        });

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !modal.hidden) {
                event.preventDefault();
                closeModal();
            }
        });

        modal.addEventListener("keydown", (event) => {
            if (event.key !== "Tab") return;

            const elements = focusableElements();
            if (!elements.length) {
                event.preventDefault();
                dialog.focus();
                return;
            }
            const first = elements[0];
            const last = elements[elements.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        });
    }

    function bindAutoFilterForms() {
        const selector = [
            "form.filter-bar[method='get']",
            "form.stock-ledger__filters[method='get']",
            "form[data-auto-filter]",
        ].join(", ");
        const categorySelector = [
            ".movement-categories a",
            ".stock-clear-button",
            "form[data-auto-filter] a.button",
            "[data-refund-pane-link]",
            "[data-async-filter-results] .pagination a",
            "[data-async-filter-results] .stock-pagination a",
        ].join(", ");
        const timers = new WeakMap();
        let activeRequest = null;

        function isFilterForm(form) {
            return form instanceof HTMLFormElement && form.matches(selector);
        }

        function formUrl(form) {
            const url = new URL(form.getAttribute("action") || window.location.href, window.location.origin);
            const values = new URLSearchParams();
            new FormData(form).forEach((value, key) => {
                if (typeof value === "string") values.append(key, value);
            });
            url.search = values.toString();
            return url;
        }

        function bindRefreshedContent() {
            bindReceiptCheckout();
            bindPaymentCountdowns();
        }

        function targetSelectorFor(source) {
            if (!(source instanceof Element)) return "";
            const directTarget = source.closest("[data-async-filter-target]")?.dataset.asyncFilterTarget;
            if (directTarget) return directTarget;
            return source.closest(".panel")?.querySelector("form[data-async-filter-target]")?.dataset.asyncFilterTarget || "";
        }

        async function refreshContent(url, { pushState = true, targetSelector = "" } = {}) {
            activeRequest?.abort();
            const controller = new AbortController();
            activeRequest = controller;
            const contentSelector = targetSelector || "[data-portal-content]";
            const currentContent = document.querySelector(contentSelector);
            currentContent?.setAttribute("aria-busy", "true");

            try {
                const response = await fetch(url, {
                    headers: {
                        Accept: "text/html",
                        "X-Requested-With": "fetch",
                    },
                    credentials: "same-origin",
                    signal: controller.signal,
                });
                if (!response.ok) throw new Error("Unable to update the filtered results.");

                const html = await response.text();
                const documentResponse = new DOMParser().parseFromString(html, "text/html");
                const replacement = documentResponse.querySelector(contentSelector);
                if (!replacement || !currentContent) throw new Error("Unable to update the filtered results.");

                currentContent.replaceWith(replacement);
                document.querySelectorAll("[data-async-filter-sync]").forEach((currentElement) => {
                    const syncKey = currentElement.dataset.asyncFilterSync;
                    if (!syncKey) return;
                    const nextElement = Array.from(documentResponse.querySelectorAll("[data-async-filter-sync]"))
                        .find((candidate) => candidate.dataset.asyncFilterSync === syncKey);
                    if (nextElement) currentElement.replaceWith(nextElement);
                });
                if (documentResponse.title) document.title = documentResponse.title;
                if (pushState) window.history.pushState({}, "", url);
                window.lucide?.createIcons();
                bindRefreshedContent();
                if (contentSelector === "[data-refund-thread]") {
                    if (replacement.querySelector("[data-refund-conversation]")) {
                        document.dispatchEvent(new CustomEvent("refund:conversation-visible"));
                    }
                }
            } catch (error) {
                if (error.name === "AbortError") return;
                window.location.assign(url);
            } finally {
                if (activeRequest === controller) activeRequest = null;
                currentContent?.removeAttribute("aria-busy");
            }
        }

        function queueFormRefresh(form) {
            window.clearTimeout(timers.get(form));
            timers.set(form, window.setTimeout(() => form.requestSubmit(), 300));
        }

        document.addEventListener("input", (event) => {
            const control = event.target;
            if (!(control instanceof HTMLInputElement) || !["search", "text"].includes(control.type) || event.isComposing) {
                return;
            }
            const form = control.closest("form");
            if (isFilterForm(form)) queueFormRefresh(form);
        });

        document.addEventListener("change", (event) => {
            const control = event.target;
            if (!(control instanceof HTMLSelectElement) && !(control instanceof HTMLInputElement)) return;
            if (control instanceof HTMLInputElement && !["checkbox", "radio"].includes(control.type)) return;
            const form = control.closest("form");
            if (isFilterForm(form)) {
                window.clearTimeout(timers.get(form));
                form.requestSubmit();
            }
        });

        document.addEventListener("submit", (event) => {
            const form = event.target;
            if (!isFilterForm(form)) return;
            event.preventDefault();
            refreshContent(formUrl(form), { targetSelector: targetSelectorFor(form) });
        });

        document.addEventListener("click", (event) => {
            const link = event.target.closest(categorySelector);
            if (!link || link.dataset.inventoryProductsLink !== undefined || event.defaultPrevented
                || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
                return;
            }
            event.preventDefault();
            refreshContent(new URL(link.href), { targetSelector: targetSelectorFor(link) });
        });

        window.addEventListener("popstate", () => {
            const targetForm = document.querySelector(`${selector}[data-async-filter-target]`);
            refreshContent(new URL(window.location.href), {
                pushState: false,
                targetSelector: targetForm?.dataset.asyncFilterTarget || "",
            });
        });
    }



    function bindInventoryProductsPagination() {
        document.addEventListener("click", async (event) => {
            const link = event.target.closest("[data-inventory-products-link]");
            if (!link) {
                return;
            }
            const region = link.closest("[data-inventory-products-region]");
            const partialUrl = link.dataset.partialUrl;
            if (!region || !partialUrl) {
                return;
            }

            event.preventDefault();
            const status = region.querySelector("[data-inventory-products-status]");
            region.classList.add("is-loading");
            if (status) {
                status.textContent = "Loading products...";
            }

            try {
                const response = await fetch(partialUrl, {
                    headers: {
                        "X-Requested-With": "fetch",
                    },
                });
                if (!response.ok) {
                    throw new Error("Products could not be loaded.");
                }
                const html = await response.text();
                const template = document.createElement("template");
                template.innerHTML = html.trim();
                const replacement = template.content.querySelector("[data-inventory-products-region]");
                if (!replacement) {
                    throw new Error("Products could not be loaded.");
                }
                region.replaceWith(replacement);
                window.history.pushState({}, "", link.href);
                const selectedType = new URL(link.href).searchParams.get("type") || "";
                const typeInput = document.querySelector("[data-inventory-products-type]");
                if (typeInput) typeInput.value = selectedType;
                if (window.lucide) {
                    window.lucide.createIcons();
                }
            } catch (error) {
                region.classList.remove("is-loading");
                if (status) {
                    status.textContent = error.message || "Products could not be loaded.";
                }
            }
        });
    }

    function bindRecipeRows() {
        const rows = document.getElementById("recipe-rows");
        const addButton = document.getElementById("add-ingredient");
        if (!rows || !addButton) {
            return;
        }

        function updateRemoveButtons() {
            const recipeRows = rows.querySelectorAll("[data-recipe-row]");
            recipeRows.forEach((row) => {
                const button = row.querySelector("[data-remove-ingredient]");
                if (button) {
                    button.disabled = recipeRows.length === 1;
                }
            });
        }

        rows.addEventListener("click", (event) => {
            const removeButton = event.target.closest("[data-remove-ingredient]");
            if (!removeButton) {
                return;
            }
            const recipeRows = rows.querySelectorAll("[data-recipe-row]");
            if (recipeRows.length <= 1) {
                return;
            }
            removeButton.closest("[data-recipe-row]").remove();
            updateRemoveButtons();
        });

        addButton.addEventListener("click", () => {
            const sourceRow = rows.querySelector("[data-recipe-row]");
            const newRow = sourceRow.cloneNode(true);
            newRow.querySelectorAll("input").forEach((input) => {
                input.value = "";
            });
            rows.appendChild(newRow);
            updateRemoveButtons();
            window.lucide?.createIcons();
        });

        updateRemoveButtons();
    }

    function bindInventoryWorkspaceModals() {
        const modals = Array.from(document.querySelectorAll("[data-inventory-modal]"));
        if (!modals.length) {
            return;
        }

        let activeModal = null;
        let returnFocus = null;
        const focusableSelector = [
            "button:not([disabled])",
            "input:not([disabled])",
            "select:not([disabled])",
            "textarea:not([disabled])",
            "a[href]",
            "summary",
            "[tabindex]:not([tabindex='-1'])",
        ].join(",");

        function updateModalQuery(name) {
            const url = new URL(window.location.href);
            if (name) {
                url.searchParams.set("modal", name);
            } else {
                url.searchParams.delete("modal");
            }
            window.history.replaceState({}, "", url);
        }

        function closeModal({ restoreFocus = true, updateUrl = true } = {}) {
            if (!activeModal) {
                return;
            }
            activeModal.hidden = true;
            activeModal = null;
            document.body.classList.remove("modal-is-open");
            if (updateUrl) {
                updateModalQuery("");
            }
            if (restoreFocus && returnFocus) {
                returnFocus.focus();
            }
            returnFocus = null;
        }

        function openModal(name, trigger = null, { updateUrl = true } = {}) {
            const modal = modals.find((item) => item.dataset.inventoryModal === name);
            if (!modal) {
                return;
            }
            if (activeModal && activeModal !== modal) {
                closeModal({ restoreFocus: false, updateUrl: false });
            }
            returnFocus = trigger || document.querySelector(`[data-inventory-modal-open="${name}"]`);
            activeModal = modal;
            modal.hidden = false;
            document.body.classList.add("modal-is-open");
            if (updateUrl) {
                updateModalQuery(name);
            }
            window.requestAnimationFrame(() => {
                const preferredFocus = modal.querySelector(".inventory-modal-body input:not([type='hidden']):not([disabled]), .inventory-modal-body select:not([disabled])")
                    || modal.querySelector("button[data-inventory-modal-close]");
                (preferredFocus || modal.querySelector("[role='dialog']"))?.focus();
            });
        }

        document.querySelectorAll("[data-inventory-modal-open]").forEach((trigger) => {
            trigger.addEventListener("click", () => openModal(trigger.dataset.inventoryModalOpen, trigger));
        });

        modals.forEach((modal) => {
            modal.querySelectorAll("[data-inventory-modal-close]").forEach((button) => {
                button.addEventListener("click", () => closeModal());
            });
        });

        document.addEventListener("keydown", (event) => {
            if (!activeModal) {
                return;
            }
            if (event.key === "Escape") {
                event.preventDefault();
                closeModal();
                return;
            }
            if (event.key !== "Tab") {
                return;
            }
            const focusable = Array.from(activeModal.querySelectorAll(focusableSelector)).filter((element) => element.offsetParent !== null);
            if (!focusable.length) {
                event.preventDefault();
                activeModal.querySelector("[role='dialog']")?.focus();
                return;
            }
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        });

        const requestedModal = new URLSearchParams(window.location.search).get("modal");
        if (requestedModal) {
            openModal(requestedModal, null, { updateUrl: false });
        }
    }

    bindPortalDrawer();
    bindNotificationMenu();
    bindSignOutConfirmation();
    bindAutoFilterForms();
    bindInventoryProductsPagination();
    bindRecipeRows();
    bindInventoryWorkspaceModals();
})();
