/* global Bancard */

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { PaymentForm } from "@payment/interactions/payment_form";

patch(PaymentForm.prototype, {
    setup() {
        super.setup(...arguments);
        this.bancardScriptLoaded = false;
    },

    async _prepareInlineForm(providerId, providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (providerCode !== "bancard") {
            return await super._prepareInlineForm(...arguments);
        }
        if (flow === "token") {
            return;
        }
        this._setPaymentFlow("direct");
    },

    async _processDirectFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        if (providerCode !== "bancard") {
            return await super._processDirectFlow(...arguments);
        }

        const processId = processingValues.bancard_process_id;
        const checkoutJsUrl = processingValues.bancard_checkout_js_url;
        const styles = processingValues.bancard_iframe_styles || {};

        if (!processId) {
            this._displayErrorDialog(
                _t("Erro Bancard"),
                _t("Não foi possível obter o identificador de sessão (process_id) da Bancard.")
            );
            this._enableButton();
            return;
        }

        try {
            await this._bancardEnsureScriptLoaded(checkoutJsUrl);
            const containerId = `bancard-iframe-container-${processingValues.provider_id}`;
            const containerEl = document.getElementById(containerId);
            if (!containerEl) {
                throw new Error(_t("Container do formulário Bancard não encontrado na página."));
            }

            containerEl.classList.remove("d-none");
            containerEl.innerHTML = "";

            const options = {
                styles: styles,
            };

            if (window.Bancard && window.Bancard.Checkout) {
                window.Bancard.Checkout.createForm(containerId, processId, options);
            } else {
                throw new Error(_t("Objeto global Bancard.Checkout indisponível."));
            }
        } catch (error) {
            this._displayErrorDialog(_t("Erro ao inicializar Bancard"), error.message || String(error));
            this._enableButton();
        }
    },

    _bancardRender3DSForm(containerId, processId, styles = {}) {
        if (window.Bancard && window.Bancard.Charge3DS) {
            window.Bancard.Charge3DS.createForm(containerId, processId, { styles });
        }
    },

    _bancardEnsureScriptLoaded(scriptUrl) {
        if (this.bancardScriptLoaded && window.Bancard) {
            return Promise.resolve();
        }
        return new Promise((resolve, reject) => {
            const existing = document.querySelector(`script[src="${scriptUrl}"]`);
            if (existing && window.Bancard) {
                this.bancardScriptLoaded = true;
                resolve();
                return;
            }
            const script = document.createElement("script");
            script.src = scriptUrl;
            script.async = true;
            script.onload = () => {
                this.bancardScriptLoaded = true;
                resolve();
            };
            script.onerror = () => {
                reject(new Error(_t("Falha ao carregar biblioteca JS da Bancard.")));
            };
            document.head.appendChild(script);
        });
    },
});
