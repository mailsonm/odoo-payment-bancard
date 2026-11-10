import { _t } from "@web/core/l10n/translation";
import { PaymentInterface } from "@point_of_sale/app/utils/payment/payment_interface";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { register_payment_method } from "@point_of_sale/app/services/pos_store";

export class PaymentBancardQR extends PaymentInterface {
    setup() {
        super.setup(...arguments);
        this.webhookResolver = null;
        this.currentHookAlias = null;
        this.pollTimer = null;
    }

    async sendPaymentRequest(cid) {
        await super.sendPaymentRequest(...arguments);
        const order = this.pos.getOrder();
        const line = order.getSelectedPaymentline();

        try {
            line.setPaymentStatus("waitingCapture");
            const infos = {
                pos_config_id: this.pos.config.id,
                pos_session_id: this.pos.config.current_session_id?.id || false,
                amount: Math.round(line.amount),
                description: `FA POS ${order.name || order.uuid || ""}`.slice(0, 60),
                pos_order_uuid: order.uuid,
            };

            const res = await this.env.services.orm.silent.call(
                "pos.payment.method",
                "bancard_qr_create_order",
                [[line.payment_method_id.id], infos]
            );

            if (!res || res.status !== "success" || !res.hook_alias) {
                this._showError(res?.message || _t("Não foi possível gerar o QR Express da Bancard."));
                return false;
            }

            this.currentHookAlias = res.hook_alias;
            line.transaction_id = res.hook_alias;
            line.setPaymentStatus("waitingCard");

            return await new Promise((resolve) => {
                this.webhookResolver = resolve;
                this._startStatusPolling(line.payment_method_id.id, res.hook_alias);
            });
        } catch (error) {
            this._showError(error?.data?.message || error?.message || String(error));
            return false;
        }
    }

    async sendPaymentCancel(order, cid) {
        await super.sendPaymentCancel(order, cid);
        this._clearPolling();
        if (!this.currentHookAlias) {
            return true;
        }

        const line = order.getSelectedPaymentline();
        const hookAlias = this.currentHookAlias;
        this.currentHookAlias = null;

        try {
            await this.env.services.orm.silent.call(
                "pos.payment.method",
                "bancard_qr_revert_order",
                [
                    [line.payment_method_id.id],
                    {
                        pos_config_id: this.pos.config.id,
                        hook_alias: hookAlias,
                    },
                ]
            );
        } catch (error) {
            this._showError(error?.data?.message || error?.message || String(error));
        }

        if (this.webhookResolver) {
            this.webhookResolver(false);
            this.webhookResolver = null;
        }
        return true;
    }

    handleBancardQRWebhook(payload) {
        if (!this.currentHookAlias || payload.hook_alias !== this.currentHookAlias) {
            return;
        }
        if (payload.state === "confirmed") {
            this._clearPolling();
            const line = this.pos.getOrder()?.getSelectedPaymentline();
            if (line) {
                line.ticket = payload.ticket_number || payload.authorization_number || payload.hook_alias;
                line.setPaymentStatus("done");
            }
            this.currentHookAlias = null;
            if (this.webhookResolver) {
                this.webhookResolver(true);
                this.webhookResolver = null;
            }
        }
    }

    _startStatusPolling(paymentMethodId, hookAlias) {
        this._clearPolling();
        this.pollTimer = setInterval(async () => {
            if (!this.currentHookAlias || this.currentHookAlias !== hookAlias) {
                this._clearPolling();
                return;
            }
            try {
                const statusRes = await this.env.services.orm.silent.call(
                    "pos.payment.method",
                    "bancard_qr_check_status",
                    [[paymentMethodId], hookAlias]
                );
                if (statusRes?.state === "confirmed") {
                    this.handleBancardQRWebhook(statusRes);
                }
            } catch {
                // Ignora falhas transitórias durante polling silencioso
            }
        }, 3000);
    }

    _clearPolling() {
        if (this.pollTimer) {
            clearInterval(this.pollTimer);
            this.pollTimer = null;
        }
    }

    _showError(msg, title) {
        this.env.services.dialog.add(AlertDialog, {
            title: title || _t("Erro Bancard VentasQR"),
            body: msg,
        });
    }
}

register_payment_method("bancard_qr", PaymentBancardQR);
