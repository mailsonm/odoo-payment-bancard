import { _t } from "@web/core/l10n/translation";
import { PaymentInterface } from "@point_of_sale/app/utils/payment/payment_interface";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { register_payment_method } from "@point_of_sale/app/services/pos_store";

export class PaymentBancardCajaPos extends PaymentInterface {
    setup() {
        super.setup(...arguments);
        this.resolver = null;
        this.currentTxToken = null;
        this.pollTimer = null;
    }

    async sendPaymentRequest(cid) {
        await super.sendPaymentRequest(...arguments);
        const order = this.pos.getOrder();
        const line = order.getSelectedPaymentline();

        try {
            line.setPaymentStatus("waitingCapture");
            const billNumber = (order.name || order.uuid || `REC-${Date.now()}`).replace(/[^\w-]/g, "").slice(0, 30);
            const infos = {
                pos_config_id: this.pos.config.id,
                pos_session_id: this.pos.config.current_session_id?.id || false,
                bill_number: billNumber,
                amount: Math.round(line.amount),
                pos_order_uuid: order.uuid,
            };

            const res = await this.env.services.orm.silent.call(
                "pos.payment.method",
                "bancard_cajapos_create_sale",
                [[line.payment_method_id.id], infos]
            );

            if (!res || res.status !== "success" || !res.tx_token) {
                this._showError(res?.message || _t("Não foi possível enviar a cobrança para o terminal POS Bancard."));
                line.setPaymentStatus("retry");
                return false;
            }

            this.currentTxToken = res.tx_token;
            line.transaction_id = res.tx_token;
            line.setPaymentStatus("waitingCard");

            return await new Promise((resolve) => {
                this.resolver = resolve;
                this._startStatusPolling(line.payment_method_id.id, res.tx_token);
            });
        } catch (error) {
            this._showError(error?.data?.message || error?.message || String(error));
            line.setPaymentStatus("retry");
            return false;
        }
    }

    async sendPaymentCancel(order, cid) {
        await super.sendPaymentCancel(order, cid);
        this._clearPolling();
        this.currentTxToken = null;
        if (this.resolver) {
            this.resolver(false);
            this.resolver = null;
        }
        return true;
    }

    _startStatusPolling(paymentMethodId, txToken) {
        this._clearPolling();
        this.pollTimer = setInterval(async () => {
            if (!this.currentTxToken || this.currentTxToken !== txToken) {
                this._clearPolling();
                return;
            }
            try {
                const statusRes = await this.env.services.orm.silent.call(
                    "pos.payment.method",
                    "bancard_cajapos_check_status",
                    [[paymentMethodId], this.pos.config.id, txToken]
                );

                if (statusRes?.is_final) {
                    this._clearPolling();
                    const line = this.pos.getOrder()?.getSelectedPaymentline();

                    if (statusRes.payment_status === "PAYMENT_CONFIRMED") {
                        if (line) {
                            line.ticket = statusRes.ticket_number || statusRes.authorization_code || txToken;
                            line.setPaymentStatus("done");
                        }
                        this.currentTxToken = null;
                        if (this.resolver) {
                            this.resolver(true);
                            this.resolver = null;
                        }
                    } else {
                        // Rejeitado, cancelado pelo cliente ou terminal offline
                        const errMsg = statusRes.response_message || _t("Transação não aprovada no terminal Bancard (%s).", statusRes.payment_status);
                        this._showError(errMsg, _t("Bancard Caja POS"));
                        if (line) {
                            line.setPaymentStatus("retry");
                        }
                        this.currentTxToken = null;
                        if (this.resolver) {
                            this.resolver(false);
                            this.resolver = null;
                        }
                    }
                }
            } catch {
                // Silencioso em caso de oscilações transitórias de rede
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
            title: title || _t("Bancard Caja POS 3.0"),
            body: msg,
        });
    }
}

register_payment_method("bancard_cajapos", PaymentBancardCajaPos);
